"""interim/ → processed/municipalities.json（スコア算出）

以下の手順を実装する:
    1. 面積あたり / 人口1万人あたりに換算して規模の差を除く
    2. 上下5パーセンタイルでウィンザライズ（都心の外れ値でスケールが潰れるのを防ぐ）
    3. min-max で 0〜100 にスケーリング
    4. 「低いほど良い」指標は 100 - score で反転
    5. 軸スコア = 軸内の指標スコアの単純平均

総合スコア:
- 重みはユーザーが動かすため、ここでは計算しない。
- Σ(軸スコア × 重み) / Σ(重み) はフロント側で計算する。

欠損は0で埋めず `value: null` + `status: "no_data"` として残す。
埋めてしまうと「データが無い自治体」が「悪い自治体」に化けるため。
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from core import municipalities as muni
from core.config import (
    BASE_CSV,
    DEMO_JSON,
    OUTPUT_JSON,
    SCHEMA_VERSION,
    ensure_dirs,
    indicator_csv,
    setup_logging,
)
from core.io_utils import parse_numeric_column, read_csv, write_json
from defs import datasets
from defs.indicators import (
    AXES,
    DEFAULT_WEIGHTS,
    INDICATOR_BY_KEY,
    INDICATORS,
    PRESETS,
    Indicator,
)

logger = logging.getLogger(__name__)

WINSOR_LOWER = 0.05
WINSOR_UPPER = 0.95

N_MUNI = len(muni.CODES)


# ---------------------------------------------------------------- 正規化の基本操作


def winsorize(s: pd.Series, lower: float = WINSOR_LOWER, upper: float = WINSOR_UPPER) -> pd.Series:
    """上下パーセンタイルで値を切り詰める。欠損はそのまま欠損で残す。"""
    valid = s.dropna()
    if valid.empty:
        return s
    return s.clip(valid.quantile(lower), valid.quantile(upper))


def minmax(s: pd.Series) -> pd.Series:
    """0〜100 にスケーリングする。全自治体が同値なら差が無いので一律50とする。"""
    valid = s.dropna()
    if valid.empty:
        return pd.Series(np.nan, index=s.index, dtype=float)
    lo, hi = float(valid.min()), float(valid.max())
    if hi == lo:
        return s.notna().map({True: 50.0, False: np.nan}).astype(float)
    return (s - lo) / (hi - lo) * 100.0


def apply_direction(scores: pd.Series, indicator: Indicator) -> pd.Series:
    """「低いほど良い」指標を反転する。"""
    return 100.0 - scores if indicator.direction == "lower_is_better" else scores


def score_indicator(values: pd.Series, indicator: Indicator) -> pd.Series:
    return apply_direction(minmax(winsorize(values)), indicator).round(1)


# ---------------------------------------------------------------- 入力の読み込み


def load_base() -> pd.DataFrame:
    """面積・人口（分母）を読む。無ければ空の枠を返す（『◯◯あたり』は欠損になる）。"""
    frame = pd.DataFrame(
        np.nan, index=pd.Index(muni.CODES, name="code"), columns=["area_km2", "population"]
    )
    if not BASE_CSV.exists():
        logger.warning(
            "%s がありません。面積・人口が無いため『◯◯あたり』の指標は算出できません。", BASE_CSV
        )
        return frame

    df = read_csv(BASE_CSV)
    df["code"] = df["code"].map(muni.normalize_code)
    df = df[df["code"].notna()].set_index("code")
    for col in frame.columns:
        if col not in df.columns:
            logger.warning("%s に %s 列がありません", BASE_CSV.name, col)
            continue
        values = parse_numeric_column(df[col])
        frame[col] = values.groupby(level=0).first().reindex(muni.CODES)
    return frame


def load_indicator_series(indicator: Indicator) -> pd.Series:
    """指標CSVを1本読み、53自治体ぶんに揃えた値の並びにする。"""
    empty = pd.Series(np.nan, index=pd.Index(muni.CODES, name="code"), dtype=float)
    path = indicator_csv(indicator.dataset_id, indicator.key)
    if not path.exists():
        logger.warning("%s がありません（加工が未実装・未実行）", path.name)
        return empty

    df = read_csv(path)
    if not {"code", "value"} <= set(df.columns):
        logger.warning("%s: code,value 列が無いため読み飛ばす", path.name)
        return empty

    codes = df["code"].map(muni.normalize_code)
    values = pd.Series(parse_numeric_column(df["value"]).to_numpy(), index=codes, dtype=float)
    values = values[values.index.notna()]
    # 集約は前段で済んでいるはずだが、取りこぼしがあっても黙って1行目を採らない
    return values.groupby(level=0).mean().reindex(muni.CODES)


def load_indicator_values() -> pd.DataFrame:
    """interim/indicators/ の指標CSVを集めて 自治体 × 指標 の表にする。"""
    frame = pd.DataFrame(index=pd.Index(muni.CODES, name="code"))
    for ind in INDICATORS:
        frame[ind.key] = load_indicator_series(ind)
        n = int(frame[ind.key].notna().sum())
        logger.info("読み込み: %-28s %2d/%d 自治体", ind.key, n, N_MUNI)
    return frame


def apply_denominator(values: pd.Series, indicator: Indicator, base: pd.DataFrame) -> pd.Series:
    """面積あたり / 人口1万人あたりに換算する。分母が無い自治体は欠損にする。"""
    if indicator.denominator == "area_km2":
        denom = base["area_km2"]
    elif indicator.denominator == "population_10k":
        denom = base["population"] / 10_000.0
    elif indicator.denominator == "population":
        denom = base["population"]
    else:
        return values
    denom = denom.replace(0, np.nan)
    if denom.isna().all():
        logger.warning(
            "[%s] 分母(%s)が空のため換算できません", indicator.key, indicator.denominator
        )
    return values / denom


# ---------------------------------------------------------------- スコア算出


def compute(values: pd.DataFrame, base: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """指標ごとに 生値 / 換算値 / スコア を作る。"""
    raw, normalized, scored = {}, {}, {}
    for ind in INDICATORS:
        series = (
            values[ind.key]
            if ind.key in values.columns
            else pd.Series(np.nan, index=values.index, dtype=float)
        )
        series = pd.to_numeric(series, errors="coerce")
        per = apply_denominator(series, ind, base)
        raw[ind.key] = series
        normalized[ind.key] = per
        scored[ind.key] = score_indicator(per, ind)
    return {
        "raw": pd.DataFrame(raw, index=values.index),
        "normalized": pd.DataFrame(normalized, index=values.index),
        "score": pd.DataFrame(scored, index=values.index),
    }


def axis_scores(scores: pd.DataFrame) -> pd.DataFrame:
    """軸スコア = 軸内の指標スコアの単純平均。全指標が欠損なら NaN（0にはしない）。"""
    out = {}
    for axis in AXES:
        keys = [
            i.key
            for i in INDICATORS
            if i.axis == axis.key and i.include_in_axis and i.key in scores.columns
        ]
        out[axis.key] = scores[keys].mean(axis=1, skipna=True).round(1) if keys else np.nan
    return pd.DataFrame(out, index=scores.index)


# ---------------------------------------------------------------- 出力


def _clean(value: object) -> float | None:
    """NaN を JSON の null にする。"""
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    if isinstance(value, (np.floating, np.integer)):
        value = value.item()
    return round(value, 4) if isinstance(value, float) else value


def build_meta(demo: bool = False) -> dict:
    used_datasets = {i.dataset_id for i in INDICATORS}
    meta: dict = {
        "generated_at": date.today().isoformat(),
        "version": SCHEMA_VERSION,
        "axes": [
            {
                "key": a.key,
                "label": a.label,
                "description": a.description,
                "indicators": [
                    {
                        "key": i.key,
                        "label": i.label,
                        "unit": i.unit,
                        "direction": i.direction,
                        "definition": i.definition,
                        "source": i.dataset_id,
                        "reference_only": not i.include_in_axis,
                    }
                    for i in INDICATORS
                    if i.axis == a.key
                ],
            }
            for a in AXES
        ],
        "default_weights": DEFAULT_WEIGHTS,
        "presets": list(PRESETS),
        "sources": datasets.sources_for(used_datasets),
    }
    if demo:
        meta["demo"] = True
        meta["note"] = "スキーマ確認用のダミーデータです。実データではありません。"
    return meta


def build_document(
    computed: dict[str, pd.DataFrame],
    axes: pd.DataFrame,
    base: pd.DataFrame,
    demo: bool = False,
) -> dict:
    doc: dict = {"meta": build_meta(demo), "municipalities": []}

    for m in muni.MUNICIPALITIES:
        entry: dict = {
            "code": m.code,
            "name": m.name,
            "kind": m.kind,
            "region": m.region,
            "area_km2": _clean(base.at[m.code, "area_km2"]),
            "population": _clean(base.at[m.code, "population"]),
            "scores": {a.key: _clean(axes.at[m.code, a.key]) for a in AXES},
            "indicators": {},
        }
        for ind in INDICATORS:
            value = _clean(computed["raw"].at[m.code, ind.key])
            item: dict = {
                "value": value,
                "score": _clean(computed["score"].at[m.code, ind.key]),
                "source": ind.dataset_id,
            }
            if ind.unit:
                item["unit"] = ind.unit
            if ind.per_key:
                item[ind.per_key] = _clean(computed["normalized"].at[m.code, ind.key])
            # フロントで分岐しやすいよう status は常に持たせる
            item["status"] = "no_data" if value is None else "ok"
            entry["indicators"][ind.key] = item
        doc["municipalities"].append(entry)
    return doc


def report_coverage(computed: dict[str, pd.DataFrame], axes: pd.DataFrame) -> None:
    """どの指標がどれだけ埋まったかを出す（欠損の把握は品質管理そのもの）。"""
    logger.info("---- カバレッジ（%d自治体中） ----", N_MUNI)
    for ind in INDICATORS:
        values = computed["raw"][ind.key]
        n = int(values.notna().sum())
        mark = "  " if n == N_MUNI else ("!!" if n == 0 else " ~")
        missing = [muni.BY_CODE[c].name for c in muni.CODES if pd.isna(values[c])]
        logger.info(
            "%s %-28s %2d/%d%s",
            mark,
            ind.key,
            n,
            N_MUNI,
            "  欠損: " + "、".join(missing) if missing else "",
        )

    logger.info("---- 軸スコア ----")
    for axis in AXES:
        s = axes[axis.key].dropna()
        if s.empty:
            logger.warning("   %-12s 算出できた自治体なし", axis.key)
            continue
        top = [f"{muni.BY_CODE[c].name} {s[c]:.0f}" for c in s.nlargest(3).index]
        bottom = [f"{muni.BY_CODE[c].name} {s[c]:.0f}" for c in s.nsmallest(3).index]
        logger.info(
            "   %-12s %2d/%d 自治体で算出  上位: %s / 下位: %s",
            axis.key,
            len(s),
            N_MUNI,
            "、".join(top),
            "、".join(bottom),
        )


# ---------------------------------------------------------------- ダミーデータ

# (区部の中心値, 多摩の中心値, ばらつき)。実データの平均・標準偏差をおおまかになぞる。
DEMO_PROFILE: dict[str, tuple[float, float, float]] = {
    "pm25_recent_avg": (5.2, 5.2, 0.4),
    "road_noise_leq": (68.0, 66.7, 1.8),
    "park_area": (1_660_000, 1_250_000, 900_000),
    "green_coverage_ratio": (2.5, 27.0, 10.0),
    "satellite_office_count": (21, 5, 12),
    "land_price_residential": (1_120_000, 260_000, 400_000),
    "npo_count": (323, 61, 150),
}


def demo_values(seed: int = 20260816) -> tuple[pd.DataFrame, pd.DataFrame]:
    """フロント開発を先に始めるためのダミー値。

    実データの傾向（区部＝サテライトオフィスと地価が高い / 多摩＝緑が多い）を
    ゆるく再現しつつ、欠損の表示確認のためにいくつか穴を空けておく。
    """
    rng = np.random.default_rng(seed)
    codes = list(muni.CODES)
    is_ward = np.array([muni.BY_CODE[c].region == "区部" for c in codes])
    n = len(codes)

    base = pd.DataFrame(
        {
            "area_km2": np.where(is_ward, rng.uniform(10, 62, n), rng.uniform(6, 226, n)),
            "population": np.where(
                is_ward,
                rng.uniform(66_000, 960_000, n),
                rng.uniform(1_700, 575_000, n),
            ).round(),
        },
        index=pd.Index(codes, name="code"),
    )

    data = {}
    for key, (ward_mu, tama_mu, sd) in DEMO_PROFILE.items():
        mu = np.where(is_ward, ward_mu, tama_mu)
        # 割合の指標が100%を超えないよう頭を押さえる
        upper = 100.0 if INDICATOR_BY_KEY[key].unit == "%" else None
        data[key] = np.clip(rng.normal(mu, sd), 0.1, upper)
    frame = pd.DataFrame(data, index=pd.Index(codes, name="code"))

    # 欠損の見え方を確認するための穴。実データで欠けている指標に合わせてある
    # （PM2.5は測定局の無い自治体、サテライトオフィスは掲載の無い自治体、
    #   公園と地価は檜原村・奥多摩町に原データが無い）。
    frame.loc[rng.choice(codes, 10, replace=False), "pm25_recent_avg"] = np.nan
    frame.loc[rng.choice(codes, 12, replace=False), "satellite_office_count"] = np.nan
    frame.loc[["13307"], "park_area"] = np.nan
    frame.loc[["13307", "13308"], "land_price_residential"] = np.nan
    return frame, base


# ---------------------------------------------------------------- エントリポイント


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="指標をスコア化して municipalities.json を作る")
    parser.add_argument(
        "--demo", action="store_true", help="ダミーデータで municipalities.sample.json を生成"
    )
    parser.add_argument("--out", type=Path, help="出力先を明示する")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    ensure_dirs()

    if args.demo:
        values, base = demo_values()
    else:
        base = load_base()
        values = load_indicator_values()

    computed = compute(values, base)
    axes = axis_scores(computed["score"])
    report_coverage(computed, axes)

    doc = build_document(computed, axes, base, demo=args.demo)
    write_json(args.out or (DEMO_JSON if args.demo else OUTPUT_JSON), doc)

    if not args.demo and axes.notna().to_numpy().sum() == 0:
        logger.warning(
            "スコアが1件も算出されていません。ingest → normalize → spatial_join の順に実行し、"
            "interim/indicators/ にファイルが出ているか確認してください。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
