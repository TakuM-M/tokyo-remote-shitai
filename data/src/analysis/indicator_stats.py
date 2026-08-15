"""指標の分布サマリ

各指標の min/max・分位点・外れ値候補と、ウィンザライズが実際に
どれだけの値を丸めているかを確認する。
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from analysis._report import (
    format_number,
    heading,
    join_names,
    print_list,
    print_table,
    truncate,
)
from core import municipalities as muni
from core.config import INDICATOR_DIR, setup_logging
from defs.indicators import INDICATOR_BY_KEY, INDICATORS, Indicator
from pipeline import score

logger = logging.getLogger(__name__)

# 箱ひげ図と同じ基準。四分位範囲の1.5倍を外れ値の目安にする。
IQR_FACTOR = 1.5

DENOM_LABEL = {"area_km2": "/km2", "population_10k": "/万人", None: "-"}


@dataclass
class Stats:
    """1指標分の集計。値はすべて「換算後」（スコア計算に入るのと同じ値）。"""

    indicator: Indicator
    values: pd.Series  # 換算後
    raw: pd.Series  # 換算前の生値

    @property
    def valid(self) -> pd.Series:
        return self.values.dropna()

    @property
    def n(self) -> int:
        return len(self.valid)

    def q(self, ratio: float) -> float:
        return float(self.valid.quantile(ratio)) if self.n else float("nan")

    @property
    def bounds(self) -> tuple[float, float]:
        """ウィンザライズの下限・上限。"""
        return self.q(score.WINSOR_LOWER), self.q(score.WINSOR_UPPER)

    def clipped(self) -> tuple[list[str], list[str]]:
        """丸められる自治体コード（下側, 上側）。"""
        if not self.n:
            return [], []
        lo, hi = self.bounds
        return (
            list(self.valid[self.valid < lo].index),
            list(self.valid[self.valid > hi].index),
        )

    def outliers(self) -> tuple[list[str], list[str]]:
        """四分位範囲から外れる自治体コード（下側, 上側）。"""
        if self.n < 4:
            return [], []
        q1, q3 = self.q(0.25), self.q(0.75)
        span = (q3 - q1) * IQR_FACTOR
        return (
            list(self.valid[self.valid < q1 - span].index),
            list(self.valid[self.valid > q3 + span].index),
        )

    @property
    def all_equal(self) -> bool:
        """全自治体が同値だと min-max が効かず、スコアが一律50になる。"""
        return self.n > 0 and self.valid.min() == self.valid.max()

    @property
    def denominator_missing(self) -> list[str]:
        """生値はあるのに分母が無くて換算できなかった自治体。"""
        return list(self.raw.index[self.raw.notna() & self.values.isna()])


def collect(verbose: bool = False) -> list[Stats]:
    """指標ごとに 生値 と 換算後の値 を用意する。

    読み込みと換算は score.py の関数をそのまま使う。ここで計算式を書き直すと、
    成果物とレポートで数字がずれたときに原因が分からなくなるため。
    """
    logging.getLogger(score.__name__).setLevel(logging.DEBUG if verbose else logging.WARNING)
    values = score.load_indicator_values().reindex(muni.CODES)
    base = score.load_base()

    out = []
    for ind in INDICATORS:
        if ind.key in values.columns:
            raw = pd.to_numeric(values[ind.key], errors="coerce")
        else:
            raw = pd.Series(np.nan, index=pd.Index(muni.CODES, name="code"), dtype=float)
        out.append(Stats(indicator=ind, values=score.apply_denominator(raw, ind, base), raw=raw))
    return out


def names(codes: list[str], limit: int) -> str:
    return join_names([muni.BY_CODE[c].name for c in codes], limit)


def upper_lower(high: list[str], low: list[str], limit: int) -> str:
    """上側・下側のどちらに当たった自治体かが分かるように並べる。"""
    parts = []
    if high:
        parts.append(f"上 {names(high, limit)}")
    if low:
        parts.append(f"下 {names(low, limit)}")
    return " / ".join(parts) if parts else "-"


def print_distribution(stats: list[Stats]) -> None:
    heading("分布（換算後の値。スコア計算に入るのと同じ値）")
    rows = [
        [
            truncate(s.indicator.key, 28),
            DENOM_LABEL[s.indicator.denominator],
            str(s.n),
            format_number(s.q(0.0) if s.n else None),
            format_number(s.q(0.25) if s.n else None),
            format_number(s.q(0.5) if s.n else None),
            format_number(s.q(0.75) if s.n else None),
            format_number(s.q(1.0) if s.n else None),
            format_number(float(s.valid.mean()) if s.n else None),
        ]
        for s in stats
    ]
    print_table(
        ["指標", "換算", "n", "最小", "25%", "中央", "75%", "最大", "平均"],
        rows,
        aligns=["left", "left", "right"] + ["right"] * 6,
    )


def print_winsorize(stats: list[Stats], limit: int) -> None:
    heading("ウィンザライズの影響（上下5%で切り詰め）")
    rows = []
    for s in stats:
        lo, hi = s.bounds
        low, high = s.clipped()
        rows.append(
            [
                truncate(s.indicator.key, 28),
                format_number(lo if s.n else None),
                format_number(hi if s.n else None),
                str(len(low)),
                str(len(high)),
                upper_lower(high, low, limit),
            ]
        )
    print_table(
        ["指標", "下限(5%)", "上限(95%)", "下側", "上側", "丸められた自治体"],
        rows,
        aligns=["left", "right", "right", "right", "right", "left"],
    )
    print("  丸めても順位は変わらない。上位・下位の値が同じ位置に揃うだけ。")


def print_outliers(stats: list[Stats], limit: int) -> None:
    heading("外れ値候補（四分位範囲の1.5倍を超える値）")
    lines = []
    for s in stats:
        low, high = s.outliers()
        if not low and not high:
            continue
        lines.append(f"{s.indicator.key}: {upper_lower(high, low, limit)}")
    print_list(lines, indent="  ")


def print_warnings(stats: list[Stats], limit: int) -> None:
    heading("スコア化にあたっての注意")
    lines = []
    for s in stats:
        if s.n == 0:
            lines.append(f"{s.indicator.key}: 値が1件も無く、スコアを算出できない")
        elif s.all_equal:
            lines.append(f"{s.indicator.key}: 全自治体が同値のため、スコアが一律50になる")
        if s.n and s.n < len(muni.CODES):
            lines.append(f"{s.indicator.key}: {len(muni.CODES) - s.n}自治体が欠損（値なし）")
        if missing := s.denominator_missing:
            lines.append(
                f"{s.indicator.key}: 分母（{s.indicator.denominator}）が無く換算できない "
                f"{len(missing)}自治体 → {names(missing, limit)}"
            )
    print_list(lines, indent="  - ")


def print_detail(s: Stats, limit: int) -> None:
    ind = s.indicator
    direction = "低いほど良い" if ind.direction == "lower_is_better" else "高いほど良い"
    heading(f"{ind.key}  {ind.label}")
    print(f"  軸: {ind.axis} / {direction} / 単位: {ind.unit or '-'} / 出典: {ind.dataset_id}")
    print(f"  換算: {DENOM_LABEL[ind.denominator]}　{ind.definition}")
    if not ind.include_in_axis:
        print("  参考指標のため軸スコアには算入されない")
    if s.n == 0:
        print("  値が1件も無い")
        return

    lo, hi = s.bounds
    low, high = s.clipped()
    print(f"  ウィンザライズ: 下限 {format_number(lo)} / 上限 {format_number(hi)}")
    print(f"  丸められる自治体: 下側 {len(low)}件 / 上側 {len(high)}件")

    scores = score.score_indicator(s.values, ind)
    order = s.values.sort_values(ascending=False, na_position="last").index
    # 分母が無い指標は生値と換算後が同じなので、列を分けない
    converted = ind.denominator is not None
    rows = []
    for code in order:
        note = "上側で丸め" if code in high else ("下側で丸め" if code in low else "")
        value = [format_number(s.raw.get(code))]
        if converted:
            value.append(format_number(s.values.get(code)))
        score_value = scores.get(code)
        rows.append(
            [
                muni.BY_CODE[code].name,
                muni.BY_CODE[code].region,
                *value,
                "-" if pd.isna(score_value) else f"{score_value:.1f}",
                note,
            ]
        )
    print()
    print_table(
        ["自治体", "区分", "生値"] + (["換算後"] if converted else []) + ["スコア", "備考"],
        rows,
        aligns=["left", "left"] + ["right"] * (3 if converted else 2) + ["left"],
    )
    out_low, out_high = s.outliers()
    if out_low or out_high:
        print(f"  外れ値候補: {upper_lower(out_high, out_low, limit)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="指標ごとの分布とウィンザライズの影響を見る")
    parser.add_argument("--indicator", metavar="KEY", help="1指標だけ全自治体の内訳を表示する")
    parser.add_argument("--names", type=int, default=5, help="1行に並べる名前の数（既定5）")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    if not INDICATOR_DIR.exists():
        logger.error(
            "%s がありません。先に make normalize / make spatial-join を実行してください。",
            INDICATOR_DIR,
        )
        return 1
    if args.indicator and args.indicator not in INDICATOR_BY_KEY:
        logger.error("indicators.py に定義の無い指標です: %s", args.indicator)
        return 1

    stats = collect(args.verbose)

    if args.indicator:
        target = next(s for s in stats if s.indicator.key == args.indicator)
        print_detail(target, args.names)
        return 0

    have = sum(1 for s in stats if s.n)
    print(f"指標の分布: {len(stats)}指標中 {have}指標に値あり（{len(muni.CODES)}自治体）")
    print_distribution(stats)
    print_winsorize(stats, args.names)
    print_outliers(stats, args.names)
    print_warnings(stats, args.names)
    print("\n  1指標の内訳は --indicator <キー> で見られる")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
