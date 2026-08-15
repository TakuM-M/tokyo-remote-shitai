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
    INDICATOR_DIR,
    OUTPUT_JSON,
    SCHEMA_VERSION,
    ensure_dirs,
    setup_logging,
)
from core.io_utils import write_json
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
    """面積・人口（分母）を読む。無ければマスタだけで空の枠を作る。"""
    if BASE_CSV.exists():
        base = pd.read_csv(BASE_CSV, dtype={"code": str})
    else:
        logger.warning(
            "%s がありません。面積・人口が無いため『◯◯あたり』の指標は算出できません。", BASE_CSV
        )
        base = pd.DataFrame(columns=["code", "name", "area_km2", "population"])

    master = muni.to_frame().loc[:, ["code", "name"]]
    merged = master.merge(base.drop(columns=["name"], errors="ignore"), on="code", how="left")
    for col in ("area_km2", "population"):
        if col not in merged.columns:
            merged[col] = np.nan
        merged[col] = pd.to_numeric(merged[col], errors="coerce")
    return merged.set_index("code")


def load_indicator_values() -> pd.DataFrame:
    """interim/indicators/*.csv を集めて 自治体 × 指標 の表にする。"""
    frame = pd.DataFrame(index=pd.Index(muni.CODES, name="code"))
    if not INDICATOR_DIR.exists():
        logger.warning("%s がありません。指標がひとつも無い状態で出力します。", INDICATOR_DIR)
        return frame

    for path in sorted(INDICATOR_DIR.glob("*.csv")):
        key = path.stem
        if key not in INDICATOR_BY_KEY:
            logger.warning("indicators.py に定義の無い指標なので無視: %s", path.name)
            continue
        df = pd.read_csv(path, dtype={"code": str})
        df["code"] = df["code"].map(muni.normalize_code)
        df = df.dropna(subset=["code"])
        series = pd.to_numeric(df.set_index("code")["value"], errors="coerce")
        frame[key] = series[~series.index.duplicated(keep="first")]
        logger.info("読み込み: %-28s %d/53 自治体", key, int(frame[key].notna().sum()))
    return frame


def apply_denominator(values: pd.Series, indicator: Indicator, base: pd.DataFrame) -> pd.Series:
    """面積あたり / 人口1万人あたりに換算する。分母が無い自治体は欠損にする。"""
    if indicator.denominator == "area_km2":
        denom = base["area_km2"]
    elif indicator.denominator == "population_10k":
        denom = base["population"] / 10_000.0
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


def _clean(value: object) -> float | None:
    """NaN を JSON の null にする。"""
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    if isinstance(value, (np.floating, np.integer)):
        value = value.item()
    return round(value, 4) if isinstance(value, float) else value


def build_document(
    computed: dict[str, pd.DataFrame],
    axes: pd.DataFrame,
    base: pd.DataFrame,
    demo: bool = False,
) -> dict:
    used_datasets = {i.dataset_id for i in INDICATORS}
    doc: dict = {
        "meta": {
            "generated_at": date.today().isoformat(),
            "version": SCHEMA_VERSION,
            "demo": True if demo else None,
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
        },
        "municipalities": [],
    }
    if demo:
        doc["meta"]["note"] = "スキーマ確認用のダミーデータです。実データではありません。"
    else:
        doc["meta"].pop("demo")

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
            score = _clean(computed["score"].at[m.code, ind.key])
            item: dict = {"value": value, "score": score, "source": ind.dataset_id}
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
    logger.info("---- カバレッジ（53自治体中） ----")
    for ind in INDICATORS:
        n = int(computed["raw"][ind.key].notna().sum())
        mark = "  " if n == 53 else ("!!" if n == 0 else " ~")
        logger.info("%s %-28s %2d/53", mark, ind.key, n)
    logger.info("---- 軸スコア ----")
    for axis in AXES:
        n = int(axes[axis.key].notna().sum())
        logger.info("   %-12s %2d/53 自治体で算出", axis.key, n)


# ---------------------------------------------------------------- ダミーデータ


def demo_values(seed: int = 20260812) -> tuple[pd.DataFrame, pd.DataFrame]:
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
            "name": [muni.BY_CODE[c].name for c in codes],
            "area_km2": np.where(is_ward, rng.uniform(10, 60, n), rng.uniform(10, 220, n)),
            "population": np.where(
                is_ward,
                rng.uniform(60_000, 950_000, n),
                rng.uniform(2_000, 580_000, n),
            ).round(),
        },
        index=pd.Index(codes, name="code"),
    )

    # (区部の中心値, 多摩の中心値, ばらつき)
    profile: dict[str, tuple[float, float, float]] = {
        "pm25_annual_avg": (11, 8.5, 1.5),
        "arterial_road_density": (4.5, 1.8, 1.0),
        "traffic_volume": (32_000, 14_000, 6_000),
        "green_coverage_ratio": (18, 42, 9),
        "park_count": (90, 55, 30),
        "walking_course_count": (12, 9, 5),
        "bicycle_lane_ratio": (14, 9, 5),
        "satellite_office_count": (28, 5, 12),
        "library_count": (11, 6, 4),
        "culture_facility_count": (9, 5, 3),
        "commute_time_avg": (18, 48, 10),
        "transfer_count_avg": (0.4, 1.4, 0.5),
        "station_density": (450, 120, 120),
        "transit_options": (26, 8, 8),
        "land_price_residential": (780_000, 230_000, 180_000),
        "housing_area_per_building": (95, 145, 25),
        "npo_count": (48, 22, 15),
        "community_facility_count": (24, 14, 8),
        "day_night_population_ratio": (185, 88, 40),
    }

    data = {}
    for key, (ward_mu, tama_mu, sd) in profile.items():
        mu = np.where(is_ward, ward_mu, tama_mu)
        values = np.clip(rng.normal(mu, sd), 0.1, None)
        data[key] = values
    frame = pd.DataFrame(data, index=pd.Index(codes, name="code"))

    # 欠損の見え方を確認するための穴
    frame.loc[rng.choice(codes, 18, replace=False), "traffic_volume"] = np.nan
    frame.loc[rng.choice(codes, 6, replace=False), "walking_course_count"] = np.nan
    frame.loc[["13307", "13308"], "bicycle_lane_ratio"] = np.nan
    return frame, base


# ---------------------------------------------------------------- エントリポイント


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="指標をスコア化して municipalities.json を作る")
    parser.add_argument(
        "--demo", action="store_true", help="ダミーデータで municipalities.sample.json を生成"
    )
    parser.add_argument("--out", type=str, help="出力先を明示する")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    ensure_dirs()

    if args.demo:
        values, base = demo_values()
        base = base.reindex(muni.CODES)
    else:
        base = load_base()
        values = load_indicator_values()

    computed = compute(values, base)
    axes = axis_scores(computed["score"])
    report_coverage(computed, axes)

    doc = build_document(computed, axes, base, demo=args.demo)
    out = Path(args.out) if args.out else (DEMO_JSON if args.demo else OUTPUT_JSON)
    write_json(out, doc)

    if not args.demo and axes.notna().sum().sum() == 0:
        logger.warning(
            "スコアが1件も算出されていません。ingest → normalize → spatial_join の順に実行し、"
            "interim/indicators/ にファイルが出ているか確認してください。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
